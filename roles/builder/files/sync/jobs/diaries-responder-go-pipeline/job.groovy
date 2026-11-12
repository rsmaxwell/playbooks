multibranchPipelineJob('diaries-responder-go-pipeline') {
    branchSources {
        git {
            id = 'diaries-responder-go-pipeline'
            remote('https://github.com/rsmaxwell/diaries-responder-go-pipeline.git')
        }
    }
}
